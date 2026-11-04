# C4 — Containers

```mermaid
C4Container
  title Sections 00-20 Containers

  Person(engineer, "Engineer / quantitative researcher")
  Person(approver, "Model validator / risk owner / deployment approver")
  Person(operator, "ML operations / incident operator")
  System_Ext(vendor, "Licensed market-data provider")
  System_Ext(calendars, "Exchange calendar source")

  System_Boundary(system, "Stock Forecasting Platform") {
    Container(cli, "CLI / research and operations worker", "Python", "Research and controlled MLOps entry points")
    Container(app, "Application Core", "Python", "Data, training, backtest, registry, inference, feedback, monitoring, and retraining use cases")
    Container(domain, "Domain", "Python standard library", "Financial, temporal, ML-evidence, lifecycle, and monitoring invariants")
    Container(provider, "Provider Adapter", "Python", "Capabilities, fetch, decode, retry, and rate limits")
    Container(ml, "Model Adapters", "Python + scikit-learn", "Baselines, estimators, and trusted artifact codec")
    Container(calendar, "Calendar Adapter", "Python + exchange_calendars", "Venue sessions")
    ContainerDb(raw, "Raw Object Store", "Content-addressed files in this release", "Exact provider bytes")
    ContainerDb(catalog, "Research Evidence Stores", "JSONL/local and in-memory adapters", "Manifests, experiments, and datasets")
    ContainerDb(mlops, "MLOps Evidence Stores", "In-memory reference adapters", "Registry, deployments, predictions, outcomes, drift, alerts, and retraining")
    ContainerDb(artifacts, "Model Artifacts", "Checksummed bytes", "Trusted model artifacts")
  }

  Rel(engineer, cli, "Runs research and batch prediction")
  Rel(approver, cli, "Reviews gates and approves promotion")
  Rel(operator, cli, "Monitors, retrains, promotes, and rolls back")
  Rel(cli, app, "Calls")
  Rel(app, domain, "Uses")
  Rel(app, provider, "Uses through ports")
  Rel(app, calendar, "Uses through ports")
  Rel(app, ml, "Uses through ports")
  Rel(app, raw, "Writes and verifies")
  Rel(app, catalog, "Records immutable research evidence")
  Rel(app, mlops, "Records controlled production evidence")
  Rel(app, artifacts, "Reads/writes checksummed artifacts")
  Rel(provider, vendor, "Fetches authorized data")
  Rel(calendar, calendars, "Queries schedules")
```

The MLOps evidence stores are intentionally in-memory reference adapters in this release. A
production deployment must replace them with transactional, durable implementations before
multi-process operation.
