# Deployment Baseline

Sections 00–20 run as one installable Python package. Local execution may use one CLI or worker
process plus local content-addressed storage. This is a research and validation topology, not
the final production deployment.

```mermaid
flowchart TB
  Developer[Developer workstation / CI runner]
  Package[stock-forecasting-platform wheel]
  Config[Validated environment configuration]
  Process[CLI / research worker]
  Raw[(Immutable raw objects)]
  Catalog[(Ingestion and experiment evidence)]
  Repos[(Dataset, feature, and market repositories)]
  Artifacts[(Checksummed model artifacts)]
  MLOps[(Registry, predictions, outcomes, monitoring, retraining)]

  Developer --> Package
  Config --> Process
  Package --> Process
  Process --> Raw
  Process --> Catalog
  Process --> Repos
  Process --> Artifacts
  Process --> MLOps
```

## Production separation candidates

Later deployment sections may separate:

- market-data ingestion and quality workers;
- feature and dataset materialization workers;
- CPU/GPU training workers;
- batch inference workers;
- outcome collection and monitoring workers;
- API and dashboard processes;
- durable model registry, prediction/outcome ledgers, and monitoring stores.

A split requires evidence for independent scaling, security, availability, change cadence, or
team ownership. The paper-backtesting module remains isolated from broker connectivity.
