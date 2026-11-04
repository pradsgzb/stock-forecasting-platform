# Acceptance Criteria — Sections 00–25

| ID | Criterion | Evidence |
|---|---|---|
| AC-001 | A clean checkout can install and run quality checks. | Bootstrap scripts and CI workflow |
| AC-002 | Domain imports contain no framework or adapter dependency. | `tests/architecture/test_import_boundaries.py` |
| AC-003 | Float input to financial value objects is rejected. | Unit tests |
| AC-004 | Money arithmetic rejects currency mismatch. | Unit tests |
| AC-005 | Naive datetimes are rejected. | Unit tests |
| AC-006 | Effective periods use start-inclusive/end-exclusive behavior. | Unit tests |
| AC-007 | Overlapping provider symbol periods for one venue are rejected. | Unit tests |
| AC-008 | A ticker change can resolve to different instruments by date. | Application test |
| AC-009 | Universe fingerprint is deterministic regardless of ordering. | Unit test |
| AC-010 | NYSE Independence Day closure is represented correctly. | Integration test |
| AC-011 | NYSE early close is represented correctly. | Integration test |
| AC-012 | Market phase identifies pre-open, open, and post-close. | Unit/integration tests |
| AC-013 | Unknown exchange calendars fail explicitly. | Integration test |
| AC-014 | Production debug configuration is rejected. | Unit test |
| AC-015 | Secret values are redacted in representations. | Unit test |
| AC-016 | Composition root creates usable services with no global mutable container. | Integration test |
| AC-017 | Provider requests are rejected when declared capabilities do not support them. | Provider SDK tests |
| AC-018 | Identical raw payloads resolve to one content-addressed object. | Raw-store tests |
| AC-019 | Raw-object tampering or descriptor mismatch is detected on read. | Raw-store tests |
| AC-020 | Ingestion resumes after a transient page failure without duplicating completed pages. | Ingestion tests |
| AC-021 | A reused idempotency key cannot identify a different request. | Ingestion tests |
| AC-022 | Pagination cursor loops and configured page/byte limits fail explicitly. | Ingestion tests |
| AC-023 | Invalid payload schemas produce a critical rejected validation report. | Quality-service tests |
| AC-024 | Critical findings reject a batch and error findings quarantine it. | Quality-service tests |
| AC-025 | A non-session bar and out-of-session event time are detected. | Quality-rule tests |
| AC-026 | Normalization cannot proceed without accepted quality status and an effective symbol mapping. | Normalization tests |
| AC-027 | Corrections append strict revisions and deletions append tombstones. | Repository/normalization tests |
| AC-028 | Historical queries return only revisions available by the cutoff. | Point-in-time tests |
| AC-029 | Adjustment factors unavailable at the cutoff cannot affect feature inputs. | Point-in-time tests |
| AC-030 | Feature calculators cannot use undeclared source bars. | Feature-pipeline tests |
| AC-031 | Feature cache identity includes set version, instrument, date, cutoff, and input fingerprint. | Feature-store tests |
| AC-032 | The complete suite retains at least 90% branch-aware coverage. | Pytest coverage gate |
| AC-033 | Relative-return labels retain target and benchmark source-bar lineage. | Label-service tests |
| AC-034 | Cross-sectional ranks inherit peer-group availability and complete peer lineage. | Label-service tests |
| AC-035 | Equivalent dataset content has the same fingerprint regardless of publication time or generated dataset ID. | Dataset domain tests |
| AC-036 | Dataset rows reject invalid source fingerprints and temporal leakage. | Dataset domain tests |
| AC-037 | Walk-forward folds purge overlapping labels and preserve one untouched final holdout. | Splitter tests |
| AC-038 | Training requests require at least one declared baseline and require each baseline to be a candidate. | Training-request tests |
| AC-039 | A training run fails if any declared baseline does not complete successfully. | Training-service tests |
| AC-040 | Candidate selection uses development folds before the final holdout is evaluated. | Training-service and experiment-event tests |
| AC-041 | Model artifacts are checksummed and untrusted deserialization is disabled by default. | Artifact-codec tests |
| AC-042 | Regression and classification reports provide task-appropriate metrics and immutable fingerprints. | Evaluation tests |
| AC-043 | Bootstrap intervals, calibration, slice analysis, and feature importance validate their evidence. | Evaluation tests |
| AC-044 | A signal cannot execute on the session it describes or after the next session has opened. | Backtest-engine tests |
| AC-045 | Paper fills apply participation, spread, slippage, fixed, and commission cost assumptions. | Backtest policy/engine tests |
| AC-046 | Drawdown breach halts risk and liquidates on a following session when market data is available. | Backtest-engine tests |
| AC-047 | Benchmark metrics require a complete aligned benchmark series. | Backtest-engine tests |
| AC-048 | Equivalent economic backtest inputs produce the same result fingerprint despite new run/order/fill IDs. | Backtest-engine tests |
| AC-049 | The complete dataset-to-training-to-artifact-to-paper-backtest vertical slice passes. | Integration test |
| AC-050 | No broker port or live-order implementation exists in Sections 00–20. | Architecture review and settings tests |

| AC-051 | A candidate cannot become champion without configured validation gates and approvals. | Registry service tests |
| AC-052 | Lifecycle, alias, and deployment changes reject stale revisions and conflicting active deployments. | Registry repository tests |
| AC-053 | Batch inference resolves only the scoped champion and verifies target and ordered feature signatures. | Inference service tests |
| AC-054 | Reusing an inference idempotency key for different inputs is rejected. | Inference service tests |
| AC-055 | Historical predictions are immutable; corrections append linked records with unchanged business identity. | Prediction-ledger tests |
| AC-056 | Outcome collection creates revisions only when source-label evidence changes. | Feedback service tests |
| AC-057 | Feedback metrics are calculated only from latest outcomes inside the requested evidence window. | Feedback service tests |
| AC-058 | Drift reports persist PSI, Jensen–Shannon, mean-shift, and missing-rate evidence and raise threshold alerts. | Monitoring tests |
| AC-059 | Retraining requests are idempotent and preserve successful or failed terminal state. | Continuous-training tests |
| AC-060 | Promotion requires sufficient outcome count, minimum improvement, validation evidence, and configured authorization. | Champion–challenger tests |
| AC-061 | Critical alerts can roll back only the current champion to its recorded predecessor. | Rollback tests |
| AC-062 | The prediction-to-feedback-to-retraining-to-promotion-to-rollback vertical slice passes. | Integration test |
| AC-063 | Online inference and automatic promotion remain disabled by default. | Settings and composition tests |
| AC-064 | No broker port, live-order route, or autonomous source-code mutation exists. | Architecture review |
| AC-065 | Paper-account, idempotency, audit, and outbox changes commit or roll back as one transaction. | Persistence contract and service tests |
| AC-066 | Exact decimal balances, prices, quantities, costs, and SLO values round-trip without binary-float conversion. | SQLite/PostgreSQL-compatible persistence tests |
| AC-067 | Audit events form a verifiable append-only hash chain and tampering is detected. | Audit repository and readiness tests |
| AC-068 | Outbox publication is retryable, respects delayed availability, and never mutates event payload identity. | Outbox dispatcher tests |
| AC-069 | Reusing an operational idempotency key with a different request is rejected. | Paper service and persistence tests |
| AC-070 | Managed database schemas upgrade through packaged Alembic migrations and support tested downgrade behavior. | Migration integration test |
| AC-071 | JWT authentication verifies signature, issuer, audience, expiry, issued-at, subject, roles, and an explicit algorithm allow-list. | Authentication tests |
| AC-072 | Paper accounts are owner scoped; audit and metrics endpoints require privileged roles. | API authorization tests |
| AC-073 | API requests enforce trusted hosts, strict schemas, body-size limits, bounded rate-limit state, and sanitized errors. | API security tests |
| AC-074 | API financial values use decimal strings and never expose a live-trading endpoint. | OpenAPI/API integration tests |
| AC-075 | Liveness and readiness are distinct; readiness checks database access and audit integrity. | Health tests |
| AC-076 | HTTP, business-operation, outbox, and health telemetry use bounded labels and expose Prometheus-compatible metrics. | Telemetry tests |
| AC-077 | SLO snapshots are immutable, exact-decimal, fingerprinted, and persist their evidence window. | SLO domain/application/persistence tests |
| AC-078 | Database races, transaction rollback, invalid migrations, authentication failures, and abuse paths have executable negative tests. | Contract, integration, and security suites |
| AC-079 | CI provisions dependency audit, CodeQL, dependency review, filesystem/secret/configuration scan, container scan, SBOM, checksum, and provenance gates. | GitHub workflows and release scripts |
| AC-080 | Runtime containers are lockfile gated, non-root, health checked, and contain no credentials. | Dockerfile and security review |
