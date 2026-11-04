# Production MLOps Architecture — Sections 16–20

## Governed lifecycle and feedback loop

```mermaid
flowchart LR
  Artifact[Checksummed model artifact] --> Candidate[Registry candidate]
  Card[Model card and evaluation] --> Candidate
  Candidate --> Gates[Validation gates and approvals]
  Gates -->|accepted| Challenger[Shadow/canary challenger]
  Gates -->|rejected| Failed[Validation failed]
  Challenger --> Compare[Champion/challenger comparison]
  Compare -->|approved improvement| Champion[Active champion]
  Compare -->|insufficient evidence| Challenger
  Champion --> Predict[Batch inference]
  Predict --> Ledger[(Immutable prediction ledger)]
  Ledger --> Outcomes[(Versioned realized outcomes)]
  Outcomes --> Feedback[Feedback metrics]
  Feedback --> Monitor[Performance and drift monitoring]
  Monitor -->|warning/critical| Alert[(Monitoring alert)]
  Alert --> Retrain[Durable retraining request]
  Retrain --> Candidate
  Alert -->|critical champion failure| Rollback[Audited rollback]
  Rollback --> Champion
```

## Prediction-to-outcome sequence

```mermaid
sequenceDiagram
  participant Worker as Batch prediction worker
  participant Registry as Model registry
  participant Features as Feature pipeline
  participant Codec as Artifact codec
  participant Ledger as Prediction ledger
  participant Outcome as Outcome collector
  participant Labels as Target label service
  participant Feedback as Feedback service
  participant Monitor as Monitoring service

  Worker->>Registry: resolve champion(scope)
  Registry-->>Worker: approved model version + artifact
  Worker->>Features: materialize(as_of, cutoff, feature set)
  Worker->>Codec: deserialize trusted checksummed artifact
  Worker->>Ledger: append idempotent immutable batch
  Note over Ledger: Predictions are frozen before outcomes are known
  Outcome->>Ledger: list matured predictions
  Outcome->>Labels: calculate exact target version
  Outcome->>Outcome: append outcome revision
  Feedback->>Outcome: read latest revisions in window
  Feedback-->>Monitor: immutable feedback summary
  Monitor->>Monitor: evaluate degradation and thresholds
  Monitor-->>Worker: alert/retraining evidence when required
```

## Promotion and rollback sequence

```mermaid
sequenceDiagram
  participant CT as ContinuousTrainingService
  participant Train as ModelTrainingService
  participant Registry as ModelRegistryService
  participant Evidence as Promotion evidence
  participant Approver as Human/policy approver
  participant Monitor as Monitoring

  CT->>Train: train leakage-safe candidate
  Train-->>CT: artifact, card, holdout evidence
  CT->>Registry: register candidate
  CT->>Registry: validate gates and approvals
  Registry-->>CT: accepted/rejected decision
  alt accepted
    CT->>Registry: stage and shadow/canary deploy
    CT->>CT: compare champion/challenger outcomes
    Approver->>CT: approve promotion
    CT->>Registry: atomic alias/deployment promotion
  end
  Monitor-->>CT: critical alert for current champion
  CT->>Registry: atomically roll back and restore predecessor
```

## Integrity rules

- Champion resolution is scoped and server-side; clients cannot select an arbitrary model.
- A prediction records the exact artifact, signature, feature snapshot, and decision cutoff.
- Prediction and outcome corrections append records rather than rewriting history.
- Drift alerts request investigation or retraining; they do not prove a challenger is better.
- Promotion and rollback are explicit registry transactions with actors, reasons, and evidence.
- No broker or live-order boundary exists.
