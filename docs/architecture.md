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
| pgvector | Persistence of deterministic 128-dimensional token-feature vectors; runtime retrieval ranks in memory |
| React console | Review queue, case inspection and release-gate evaluation |
| Zendesk app | Ticket context, private analysis and approval action |
| Jira callback | Verified issue key and final handoff transition |

## Model providers

`DeterministicDraftProvider` makes local and CI evaluation reproducible. `BedrockDraftProvider` supplies the hosted inference path with request timeout and output-token limits.

Provider selection does not change the policy layer. Retrieval, route gates, citations, audit and human-review requirements stay within the application.

The Bedrock adapter implements hosted inference, including a configurable open-weight model ID. This is model integration, not training, fine-tuning or self-hosting.

## Retrieval contract

`HybridRetriever` chunks the approved articles and combines lexical overlap with cosine similarity over SHA256 token-feature hashes. The API constructs it from the fixture dataset. Search runs in memory; the presence of pgvector storage does not mean the inspected request path performs a database similarity query.

The highest retrieval score is exposed as confidence for routing. It is a heuristic score, not a calibrated probability of correctness or a learned semantic embedding.

## Evaluation contract

The 40 synthetic cases form a fixed regression suite. Route accuracy compares expected routes, citation recall compares expected article IDs, and risk recall compares defined flags. Grounded-draft rate checks that citation markers identify retrieved documents; it does not assess every claim in the draft. Unsafe-draft rate checks whether a non-draft route has a draft. Sensitive-data leak rate uses the configured regex redaction rules, not a comprehensive privacy test.

Historical passing percentages and hosted latency apply to the recorded dataset and provider run. Deterministic local/CI generation is separate from that run.

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
