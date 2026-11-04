# Threat Model — Sections 21–25

## Protected assets

- database credentials and JWT verification material;
- paper-account balances, positions, orders, and fills;
- audit, idempotency, outbox, prediction, and model-governance evidence;
- model artifacts and their checksums;
- release artifacts, workflow identity, SBOMs, and provenance.

## Principal threats and controls

| Threat | Primary controls |
|---|---|
| Token forgery or algorithm substitution | Configured algorithm allow-list, signature, issuer, audience, expiry, issued-at, and subject validation |
| Broken object authorization | Server-resolved principal, owner scoping, role dependencies, negative authorization tests |
| Duplicate financial command | Principal/operation/key idempotency identity, request hash, immutable replay response |
| Partial write or lost integration event | Unit of work and transactional outbox |
| Audit deletion or alteration | Append-only sequence, previous-hash chain, independent integrity check |
| Database race | Optimistic revisions, unique constraints, transaction rollback |
| Request abuse | Trusted hosts, body limit, bounded rate limiter, strict schemas, pagination limits |
| Sensitive telemetry leakage | Structured allow-listed fields and low-cardinality metric labels |
| Malicious model artifact | Hash verification, trusted codec boundary, deserialization disabled by default |
| Dependency or workflow compromise | Lockfile, dependency review, CodeQL, Trivy, action SHA pinning, SBOM and attestation |
| Container privilege escalation | Non-root runtime user, minimal image, no bundled credentials |
| Unauthorized live execution | No broker port or live-order endpoint; production setting rejects live trading |

## Residual risks

The in-memory rate limiter is a bounded single-process reference implementation, not a distributed
abuse-control service. A multi-instance deployment must replace it with a shared, atomic limiter.
The internal dashboard is intentionally minimal and is not a public consumer interface. Durable
adapters must be supplied for every enabled research repository in a managed deployment.
