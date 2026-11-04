# Security and Operational Incident Runbook

## First actions

1. Protect participant, account, credential, and model-artifact confidentiality.
2. Revoke compromised tokens or keys and disable affected ingress.
3. Preserve logs, audit events, database snapshots, container digests, and workflow evidence.
4. Establish an incident commander, timeline, severity, and communications channel.
5. Contain the failure without mutating historical audit or prediction evidence.

## Examples

- **Credential exposure:** revoke, rotate, search access evidence, and invalidate sessions.
- **Artifact compromise:** block deserialization, quarantine the artifact, restore the last trusted
  champion, and verify its checksum and provenance.
- **Database corruption:** stop writers, restore into isolation, verify audit chains and financial
  reconciliation, then perform controlled cutover.
- **Unauthorized API use:** revoke the principal, preserve request/correlation IDs, and review
  owner-scoped and privileged operations.
- **Model degradation:** use governed rollback; do not alter historical predictions or outcomes.

## Closure

Document root cause, affected assets and periods, containment, recovery evidence, required
notifications, corrective actions, owners, deadlines, and effectiveness checks.
