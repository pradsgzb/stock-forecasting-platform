# Model Development and Paper-Backtesting Architecture

## End-to-end flow

```mermaid
flowchart LR
  PIT[Point-in-time feature pipeline] --> Labels[Versioned target labels]
  Labels --> Dataset[Immutable dataset snapshot]
  PIT --> Dataset
  Dataset --> Split[Purged walk-forward split plan]
  Split --> Training[Candidate training and tuning]
  Plugins[Model plugin registry] --> Training
  Training --> Events[(Append-only experiment events)]
  Training --> Evaluation[Predictive evaluation]
  Evaluation --> Card[Model card]
  Training --> Artifact[(Checksummed model artifact)]
  Card --> Research[Approved research candidate]
  Artifact --> Research
  Research --> Signals[Immutable forecast signals]
  Signals --> Backtest[Next-session paper backtester]
  Market[Point-in-time backtest bars] --> Backtest
  Backtest --> Evidence[Equity, fills, risk, benchmark, metrics]
```

## Holdout isolation

```mermaid
sequenceDiagram
  participant D as Dataset snapshot
  participant S as Splitter
  participant T as Training service
  participant P as Model plugins
  participant E as Evaluator
  participant A as Artifact codec

  T->>D: load immutable dataset version
  T->>S: use recorded split plan
  loop development folds only
    T->>P: fit candidate on fold train indices
    T->>E: evaluate on fold validation indices
  end
  T->>T: select by primary metric
  T->>P: refit selected candidate on all development indices
  T->>E: evaluate once on final holdout
  T->>A: serialize checksummed artifact
  T-->>T: emit model card and append-only events
```

Candidate search, feature selection, and threshold choice must not inspect the final holdout.
The holdout report is generated only after selection is complete.

## Backtest timing

```mermaid
sequenceDiagram
  participant M as Model/research process
  participant L as Signal ledger input
  participant B as Paper backtester
  participant P as Market bars
  participant R as Risk and cost policies

  M->>L: forecast(as_of=T, generated_at after close T)
  B->>L: activate only when as_of < session date
  B->>P: request next-session open bar
  B->>B: reject signal generated after that open
  B->>R: construct bounded target weights
  B->>R: apply participation, spread, slippage, and commission
  B->>B: simulate fill and update cash/positions
  B->>P: mark portfolio at session close
  B->>B: evaluate drawdown and halt policy
  B-->>M: immutable fills, equity curve, metrics, fingerprint
```

## Trust boundaries

- Dataset, split, model, and backtest fingerprints are evidence; generated IDs are not treated
  as content.
- Model plugins are trusted code loaded by configuration, not tenant-supplied executable code.
- Python/joblib deserialization is disabled by default because it can execute code.
- Backtest inputs are research records, not broker orders.
- A signal cannot execute on the same session it describes or after its permitted execution
  timestamp.
- Benchmark metrics require one benchmark bar for every simulated session.
