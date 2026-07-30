# Operations

## Local checks

```bash
make backend
make frontend
make zendesk-app
make evaluate
docker compose config --quiet
terraform -chdir=deploy/aws init -backend=false
terraform -chdir=deploy/aws validate
```

## Release gates

The fixed evaluation must pass before deployment. Backend formatting, lint, types and tests run separately from the two TypeScript applications so a UI packaging failure cannot be hidden by a backend result.

## Runtime health

The API exposes `/v1/healthz`, request IDs and Prometheus metrics. The web container exposes `/healthz`. CloudWatch alarms cover load-balancer health, service availability, task count, database health and application error signals.

## Rollback

Application images should be pinned by immutable digest. ECS deployment circuit breakers stop a failed rollout, and the previous task definition remains the rollback target.

## Provider activation

Zendesk and Jira handoffs remain disabled until tenant settings, secure tokens and an exact ticket allowlist are supplied. The default configuration cannot write to either provider.
