# Zendesk AI Support Copilot

A human-reviewed support system that retrieves approved knowledge, produces cited private suggestions, applies routing and safety policy, and hands approved engineering escalations from Zendesk to Jira.

| | |
| --- | --- |
| Status | Deployed privately on AWS |
| Role | Product discovery, backend, retrieval, evaluation, frontend, provider integration and cloud delivery |
| Stack | Python, FastAPI, React, TypeScript, PostgreSQL, pgvector, AWS Bedrock, Zendesk, Jira, Terraform |

## Support workflow

```text
Zendesk ticket
      │
      ▼
approved knowledge retrieval
      │
      ▼
draft, escalate or block
      │
      ├── citations and confidence
      ├── PII and payment-data checks
      ├── injection and unsupported-claim checks
      └── review_required = true
                    │
                    ▼
             human decision
                    │
           approved escalation only
                    ▼
          Zendesk private note and tag
                    │
                    ▼
               Jira issue
```

The system has no public-reply route. Suggestions remain private, every decision requires review, and the engineering handoff is restricted to an explicit Zendesk ticket allowlist.

![Human-reviewed support console](assets/human-reviewed-support-console.png)

## Application architecture

The FastAPI service owns ticket ingestion, retrieval, policy, suggestions, audit records, evaluation and handoff state. PostgreSQL and pgvector provide durable application and retrieval storage. Two React/TypeScript interfaces consume the same API:

- an authenticated operator console for review and evaluation;
- a private Zendesk sidebar app for ticket-scoped analysis and approved escalation.

The production deployment uses a Cognito-authenticated Application Load Balancer, ECS Fargate services, private RDS, Secrets Manager, CloudWatch and immutable container images.

![AWS application architecture](assets/aws-architecture.png)

## Retrieval and safety

Eight approved knowledge articles support the fixed evaluation set. The retriever combines lexical and semantic scoring, returns document-level citations and keeps generated text bounded.

Policy checks cover:

- prompt injection and instruction override attempts;
- payment card, credential, token and government-ID content;
- incident routing and unsupported restoration times;
- financial review thresholds;
- unsupported requests and low-confidence retrieval;
- citation presence and draft grounding.

The deterministic provider supports repeatable local tests. AWS Bedrock can be selected through configuration for the deployed model path.

## Evaluation

[`data/support-cases.json`](data/support-cases.json) contains 40 synthetic cases across `draft`, `escalate` and `block` routes.

The release gate requires:

- 100% route accuracy;
- at least 80% citation recall;
- 100% risk recall;
- no draft on blocked or escalated cases;
- citations for every generated draft;
- human review on every case;
- no sensitive-data leakage in generated text.

![Evaluation release gate](assets/evaluation-release-gate.png)

## Engineering handoff

An escalation can move to Jira only after a human approves it in the Zendesk sidebar. The service atomically claims the handoff before the provider write, records the verified Zendesk response and accepts a protected Jira callback.

Repeated approvals reuse the existing handoff. A fast Jira callback cannot be overwritten by a slower dispatch transition.

![Zendesk to Jira engineering handoff](assets/jira-engineering-handoff.png)

## Run locally

Requirements: Python 3.12, [`uv`](https://docs.astral.sh/uv/), Node.js and npm.

```bash
uv sync --frozen --python 3.12
npm --prefix frontend ci
npm --prefix zendesk-app ci
make backend
make frontend
make zendesk-app
make evaluate
```

Run the API with the deterministic provider:

```bash
uv run uvicorn copilot.api.main:app --reload
```

Run the operator console in another terminal:

```bash
npm --prefix frontend run dev
```

Docker Compose starts PostgreSQL, the API and the web application on `http://127.0.0.1:8080`:

```bash
docker compose up --build
```

## Production boundary

The committed dataset and tests are synthetic. Provider credentials, tenant identifiers, allowed production ticket IDs, private run receipts and deployment state are excluded.

The deployed commissioning run used controlled support data. Its evaluation and integration results do not represent customer traffic, general model accuracy, cost savings or response-time improvement.

## Repository contents

```text
src/copilot/     API, domain, retrieval, policy, evaluation and integrations
frontend/        operator console
zendesk-app/     private ticket-sidebar application
tests/           backend unit and integration tests
data/            40-case synthetic evaluation set
migrations/      PostgreSQL and pgvector schema
deploy/aws/      Terraform application infrastructure
assets/          selected application and architecture screens
docs/            architecture, security and operating notes
```

- [Architecture](docs/architecture.md)
- [Security model](docs/security.md)
- [Operations](docs/operations.md)

