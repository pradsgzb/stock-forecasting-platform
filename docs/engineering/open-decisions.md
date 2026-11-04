# Open Decisions

| ID | Decision required | Options | Default until resolved |
|---|---|---|---|
| OD-001 | Initial licensed market-data provider | Exchange feed, commercial aggregator, broker API | Synthetic/test fixtures only |
| OD-002 | Primary production cloud | GCP, Azure, AWS, private infrastructure | Cloud-neutral boundaries |
| OD-003 | Workflow orchestrator | Temporal, Dagster, Airflow, Prefect | Direct application services |
| OD-004 | Production model/experiment registry | MLflow, managed service, internal platform | Internal ports and local evidence only |
| OD-005 | Transactional persistence | PostgreSQL deployment model | Repository ports plus local/in-memory adapters |
| OD-006 | Authoritative NSE calendar | Licensed source or validated custom calendar | Not enabled; never alias to XBOM |
| OD-007 | Initial production target | Return, direction, distribution, rank | Multiple research targets; no production target selected |
| OD-008 | Model promotion automation | Manual, semi-automated, policy-automated | Human-gated semi-automation in later section |
| OD-009 | User-facing web stack | React/TypeScript, server-rendered UI | Deferred to dashboard/API section |
| OD-010 | Artifact signing and registry trust | Sigstore, cloud KMS, internal signing | Checksum only; loading disabled by default |
| OD-011 | Production backtest engine depth | Daily bars, intraday bars, order-book simulator | Daily, next-session, long-only paper engine |
| OD-012 | Shorting and borrow model | Excluded, simple borrow, prime-broker feed | Excluded |
