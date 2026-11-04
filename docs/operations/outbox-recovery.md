# Transactional Outbox Recovery Runbook

1. Confirm the business transaction committed and identify the pending outbox event.
2. Verify its payload fingerprint and aggregate identity.
3. Correct the downstream outage or credential problem; do not edit the event payload.
4. Resume the dispatcher. Publication is at least once, so verify downstream idempotency.
5. Confirm the event moves to published state and records its publication timestamp.
6. When retries are exhausted, retain the failure evidence and create an operational incident.

Never issue a second business command solely to recreate an event. Never mark an event published
without evidence from the publisher boundary.
