# Security Policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Report it privately to the repository
security contact and include reproduction steps, affected versions, potential impact, and any
known exploitation evidence. Do not include real credentials, licensed data, or private user data
in the report.

## Supported versions

Only the current `main` branch and the latest tagged release are supported during the alpha phase.

## Security invariants

- Never commit credentials, bearer tokens, private keys, or licensed raw market data.
- Treat provider payloads, uploaded configuration, model artifacts, and serialized objects as
  untrusted until validated.
- Do not load arbitrary pickle/joblib content. The trusted-artifact adapter remains disabled by
  default and verifies its checksum before an explicitly authorized load.
- Keep live trading disabled. No broker adapter or live-order route is approved.
- Validate JWT signature, issuer, audience, time claims, subject, roles, and algorithms.
- Enforce authorization server side; UI visibility is not a security boundary.
- Exclude secrets and high-cardinality business identifiers from logs, traces, and metrics.
- Preserve audit, idempotency, outbox, prediction, and financial evidence during incidents.

## Required release controls

- resolver-generated and reviewed dependency lock;
- Ruff, strict Pyright, Bandit, tests, and branch coverage;
- dependency audit and dependency review;
- CodeQL;
- filesystem, secret, configuration, and container scanning;
- non-root runtime image;
- SBOM, SHA-256 checksums, and provenance attestation;
- pinned third-party GitHub Actions; and
- documented review of any time-bounded vulnerability exception.

## Incident handling

Immediately revoke exposed credentials, preserve evidence, contain affected ingress, and follow
`docs/operations/incident-response.md`. Rotate a credential even when exploitation has not yet
been demonstrated.
