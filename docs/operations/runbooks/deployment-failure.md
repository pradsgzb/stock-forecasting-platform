# Runbook: software deployment failure

## Trigger

Migration Job failure, readiness failure, rollout timeout, startup crash, security policy rejection, or post-deployment SLO breach.

## Response

1. Stop further promotion and retain release manifest, image digest, deployment plan, and cluster events.
2. Determine whether the migration completed and whether rollback is schema-compatible.
3. If workloads are unhealthy and the previous release remains compatible, redeploy its approved digest.
4. If a destructive or partially completed migration prevents rollback, keep traffic on the healthy prior environment and apply a reviewed forward repair.
5. Verify API and worker rollouts, readiness, outbox delivery, and database revision.
6. Record the failed release and do not reuse its version.

Never use a mutable image tag or manually edit a running container during incident recovery.
