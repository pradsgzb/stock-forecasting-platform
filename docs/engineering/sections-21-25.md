# Sections 21–25 Engineering Specification

## Purpose

Sections 21–25 add the operational boundary required to run the research and MLOps platform as a
controlled service. The delivery covers transactional operational persistence, an authenticated
internal API, a paper-trading operations view, health/SLO evidence, expanded verification, and
software-supply-chain controls.

The delivery does **not** add a broker adapter, live-order routing, investment recommendations, or
authority to deploy capital. All order workflows terminate in the paper-account ledger.

## Section 21 — Persistence, events, auditing, and migrations

The operational store uses SQLAlchemy 2 and an explicit unit-of-work boundary. PostgreSQL is the
managed-runtime target; SQLite is supported for deterministic local development and tests.
Alembic migrations are packaged with the wheel and are the only supported managed-environment
schema-change path.

A single transaction may persist:

- a paper account or paper execution;
- an idempotency record;
- a tamper-evident audit event;
- one or more transactional outbox events; and
- exact-decimal financial state.

The audit ledger is append-only and hash chained. The outbox uses at-least-once delivery with
idempotent consumers rather than promising impossible global exactly-once delivery. Failed
publication retains bounded retry evidence and can be replayed from the durable row.

Existing research repositories remain behind ports. Development defaults may use deterministic
in-memory or local content-addressed adapters; a managed deployment must supply durable adapters
for every enabled research workload rather than treating those defaults as production storage.

## Section 22 — Secured operations API and dashboard

The FastAPI boundary provides:

- liveness and readiness endpoints;
- authenticated metrics;
- versioned system information;
- paper-account creation, retrieval, listing, and paper-order execution;
- read-only audit, monitoring-alert, and prediction views; and
- a minimal internal operations dashboard.

The API applies strict Pydantic request contracts, exact decimal strings, JWT issuer/audience/
algorithm validation, role checks, trusted-host enforcement, body-size limits, bounded reference
rate limiting, correlation IDs, security headers, and RFC 9457-style problem responses.
Unexpected errors are logged with request correlation but returned without stack traces or
internal details.

## Section 23 — Observability, health, and SLO evidence

OpenTelemetry spans and Prometheus metrics cover HTTP requests, paper-trading operations,
health checks, outbox publication, and SLO evaluation. Labels are deliberately low cardinality;
direct instrument, account, user, and prediction identifiers are not metric labels.

Readiness verifies operational-database access and audit-chain integrity. SLO measurements are
immutable exact-decimal snapshots containing their objective, observation window, measured value,
error-budget status, and content fingerprint.

## Section 24 — Expanded verification strategy

The suite adds:

- reusable persistence contract tests;
- migration upgrade/downgrade tests;
- transaction rollback and optimistic-concurrency tests;
- exact-decimal round-trip tests;
- audit-chain tamper detection;
- outbox retry and delayed-availability tests;
- JWT claim, issuer, audience, signature, and role tests;
- authorization, tenant/owner scoping, request-limit, rate-limit, and trusted-host tests;
- paper-account accounting and risk-limit tests;
- API end-to-end tests; and
- SLO, health, telemetry, and failure-path tests.

The repository retains a branch-aware coverage floor of 90 percent, architecture-boundary tests,
strict typing, linting, package-build checks, and installed-artifact verification.

## Section 25 — Security and software-supply-chain controls

The delivery includes:

- least-privilege role separation;
- externally managed JWT verification keys;
- no browser token storage or implicit authentication flow;
- credential redaction and structured logging controls;
- dependency and CodeQL workflows;
- filesystem, secret, configuration, and container vulnerability scanning;
- a non-root, lockfile-gated runtime image;
- dependency SBOM generation;
- release checksums and provenance attestation;
- pinned third-party GitHub Actions;
- a threat model and incident runbooks; and
- checksummed model artifacts with untrusted deserialization disabled by default.

## Safety boundary

These sections must not:

- expose a broker or exchange order-routing interface;
- treat paper fills as evidence of executable market liquidity;
- accept caller-supplied authorization decisions;
- place sensitive identifiers in metric labels or ordinary logs;
- acknowledge a regulated or financial write before its transaction commits;
- mutate audit history or silently rewrite idempotent responses;
- load untrusted serialized Python objects; or
- claim that a security control or successful test guarantees profitable forecasting.
