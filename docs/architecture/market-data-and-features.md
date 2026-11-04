# Market Data and Feature Architecture

## Component Flow

```mermaid
flowchart LR
  Vendor[Market-data vendor] --> Adapter[Provider adapter]
  Adapter --> Ingestion[Ingestion service]
  Ingestion --> Raw[(Immutable raw objects)]
  Ingestion --> Catalog[(Manifests and checkpoints)]
  Raw --> Quality[Decode, reconcile, validate]
  Catalog --> Quality
  Quality --> Report[(Validation reports)]
  Quality -->|accepted only| Normalize[Normalization service]
  Instrument[Effective-dated instrument master] --> Normalize
  Normalize --> Bars[(Append-only bar revisions)]
  Actions[(Adjustment-factor revisions)] --> PIT[Point-in-time price service]
  Bars --> PIT
  Calendar[Exchange calendar port] --> PIT
  PIT --> Features[Feature pipeline]
  Calculators[Versioned calculators] --> Features
  Features --> Store[(Optional feature store)]
```

## Ingestion Sequence

```mermaid
sequenceDiagram
  participant W as Worker
  participant R as Provider registry
  participant P as Provider adapter
  participant O as Raw object store
  participant C as Ingestion catalog

  W->>C: find_completed(idempotency_key)
  alt completed
    C-->>W: immutable manifest
  else new or resumable
    W->>C: load checkpoint
    loop each page
      W->>R: resolve provider
      W->>P: fetch(request, cursor)
      P-->>W: opaque page bytes + next cursor
      W->>O: put(bytes)
      O-->>W: digest descriptor
      W->>C: save checkpoint
    end
    W->>C: save immutable completed manifest
    W->>C: clear checkpoint
  end
```

## Correction and Cutoff Semantics

```mermaid
sequenceDiagram
  participant N as Normalizer
  participant B as Bar repository
  participant T as Point-in-time service
  participant F as Feature pipeline

  N->>B: append revision 0
  N->>B: append revision 1 superseding revision 0
  N->>B: append tombstone revision 2
  T->>B: as_known_at(cutoff A)
  B-->>T: revision 0
  T->>B: as_known_at(cutoff B)
  B-->>T: revision 1
  T->>B: as_known_at(cutoff C)
  B-->>T: no active bar (tombstone)
  T-->>F: leakage-checked input history
  F-->>F: calculate and verify source lineage
```

## Trust Boundaries

- Provider payloads are untrusted until checksum verification, schema decoding, and quality
  validation complete.
- Validation never changes source bytes.
- Normalization accepts only reports in an accepted state.
- Feature calculators receive domain-owned decimal views, not provider objects or raw JSON.
- A feature snapshot is identified by feature-set version, instrument, as-of date, decision
  cutoff, and input fingerprint.
