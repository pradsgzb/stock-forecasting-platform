# Key Sequences

## Register and resolve a provider symbol

```mermaid
sequenceDiagram
  actor User
  participant CLI
  participant Service as InstrumentMasterService
  participant Repo as InstrumentRepository
  participant Domain as Instrument aggregate

  User->>CLI: register instrument
  CLI->>Service: register(command)
  Service->>Domain: create validated aggregate
  Service->>Repo: add(instrument)
  Repo-->>Service: stored
  Service-->>CLI: InstrumentId

  User->>CLI: resolve provider/symbol/as-of
  CLI->>Service: resolve_symbol(query)
  Service->>Repo: find_by_symbol(...)
  Repo-->>Service: matching instrument
  Service-->>CLI: immutable instrument
```

## Query a trading session

```mermaid
sequenceDiagram
  actor User
  participant CLI
  participant Container
  participant Port as CalendarProvider
  participant Adapter as ExchangeCalendarsProvider
  participant Library as exchange_calendars

  User->>CLI: session --mic XNYS --date 2025-07-03
  CLI->>Container: resolve dependencies
  CLI->>Port: session(MIC, date)
  Port->>Adapter: concrete call
  Adapter->>Library: query venue schedule
  Library-->>Adapter: pandas timestamps
  Adapter->>Adapter: validate and convert to UTC domain types
  Adapter-->>CLI: TradingSession
  CLI-->>User: JSON-safe output
```

## Ingest, validate, normalize, and materialize features

```mermaid
sequenceDiagram
  participant Worker
  participant Provider
  participant Raw as RawObjectStore
  participant Catalog as IngestionCatalog
  participant Quality
  participant Reports
  participant Normalize
  participant Bars
  participant PIT as PointInTimePriceService
  participant Features as FeaturePipeline

  Worker->>Provider: fetch_price_bars(request, cursor)
  Provider-->>Worker: opaque page
  Worker->>Raw: put(page bytes)
  Worker->>Catalog: save checkpoint / manifest
  Worker->>Quality: validate(manifest)
  Quality->>Raw: read and verify each page
  Quality->>Provider: decode_price_bars(page)
  Quality->>Reports: add immutable report
  alt accepted
    Worker->>Normalize: normalize(validated batch)
    Normalize->>Bars: append revision or tombstone
    Worker->>Features: materialize(set, instrument, as_of, cutoff)
    Features->>PIT: feature_history(..., cutoff)
    PIT-->>Features: leakage-checked inputs
    Features-->>Worker: versioned feature snapshot
  else quarantined or rejected
    Quality-->>Worker: stop downstream processing
  end
```

## Build a dataset and train a governed research model

```mermaid
sequenceDiagram
  participant Worker
  participant Feature as FeaturePipeline
  participant Label as TargetLabelService
  participant Dataset as DatasetBuilder
  participant Split as PurgedWalkForwardSplitter
  participant Train as ModelTrainingService
  participant Plugins as ModelPluginRegistry
  participant Eval as ModelEvaluationService
  participant Evidence as ExperimentTracker
  participant Artifact as ModelArtifactCodec

  Worker->>Dataset: build(feature set, target, points)
  Dataset->>Feature: materialize(as_of, decision cutoff)
  Dataset->>Label: calculate(as_of, outcome cutoff)
  Dataset-->>Worker: immutable dataset snapshot
  Worker->>Split: split(dataset, walk-forward policy)
  Split-->>Worker: folds + final holdout
  Worker->>Train: train(request)
  Train->>Evidence: append STARTED
  loop every candidate and development fold
    Train->>Plugins: fit model
    Train->>Eval: evaluate validation predictions
    Train->>Evidence: append trial result
  end
  Train->>Train: require all declared baselines and select candidate
  Train->>Plugins: refit on all development rows
  Train->>Eval: evaluate once on final holdout
  Train->>Artifact: serialize checksummed artifact
  Train->>Evidence: append model and completion evidence
  Train-->>Worker: training result + model card
```

## Execute a paper backtest

```mermaid
sequenceDiagram
  participant Researcher
  participant Engine as BacktestEngine
  participant Signals as Forecast signals
  participant Bars as Backtest bars
  participant Policy as Portfolio policy
  participant Costs as Execution cost model

  Researcher->>Engine: run(bars, signals, config)
  loop every session
    Engine->>Signals: activate only prior-date signals available by open
    Engine->>Policy: calculate bounded target weights
    Engine->>Costs: apply participation, spread, slippage, and commission
    Engine->>Engine: update cash and positions
    Engine->>Bars: mark positions at close
    Engine->>Engine: calculate drawdown and risk halt
  end
  Engine-->>Researcher: immutable fills, equity, benchmark metrics, fingerprint
```

## Govern a model, predict, observe outcomes, and monitor

```mermaid
sequenceDiagram
  participant Trainer as Training service
  participant Registry as Model registry
  participant Approver as Validators/approvers
  participant Inference as Batch inference
  participant Ledger as Prediction ledger
  participant Outcome as Outcome collector
  participant Feedback as Feedback service
  participant Monitor as Monitoring service

  Trainer->>Registry: register candidate(artifact, model card)
  Approver->>Registry: submit gates and approvals
  Registry->>Registry: stage and deploy shadow challenger
  Approver->>Registry: promote assigned challenger
  Inference->>Registry: resolve scoped champion
  Inference->>Ledger: append immutable idempotent batch
  Outcome->>Ledger: select matured predictions
  Outcome->>Outcome: append label-linked outcome revisions
  Feedback->>Outcome: aggregate latest revisions in window
  Monitor->>Feedback: evaluate drift and performance
  Monitor-->>Registry: alert/retraining/rollback evidence
```

## Controlled retraining, promotion, and rollback

```mermaid
sequenceDiagram
  participant Monitor
  participant CT as ContinuousTrainingService
  participant Train as ModelTrainingService
  participant Registry as ModelRegistryService
  participant Approver

  Monitor->>CT: request retraining(idempotency key, evidence)
  CT->>Train: train with point-in-time dataset and holdout isolation
  Train-->>CT: candidate artifact and evaluation evidence
  CT->>Registry: register and validate candidate
  Registry-->>CT: accepted/rejected promotion decision
  alt accepted
    CT->>Registry: deploy shadow/canary challenger
    CT->>CT: compare champion and challenger outcomes
    Approver->>CT: authorize promotion
    CT->>Registry: atomically promote challenger
  end
  Monitor-->>CT: critical alert for current champion
  CT->>Registry: atomically roll back and restore recorded predecessor
```

## Transactional paper order and outbox publication

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Service as PaperTradingService
    participant UOW as OperationalUnitOfWork
    participant DB as Operational database
    participant Dispatcher as OutboxDispatcher
    participant Publisher as EventPublisher

    Client->>API: JWT + paper order + idempotency key
    API->>Service: Authorized principal and validated request
    Service->>UOW: Begin transaction
    UOW->>DB: Load idempotency record and account
    Service->>Service: Apply price freshness, cash, position, and notional policy
    UOW->>DB: Save account, order, fill, audit, idempotency response, outbox event
    UOW->>DB: Commit
    Service-->>Client: Exact-decimal paper result
    Dispatcher->>DB: Read available pending events
    Dispatcher->>Publisher: Publish immutable event
    Dispatcher->>DB: Mark published or record retry evidence
```
