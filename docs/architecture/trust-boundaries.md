# Trust Boundaries

```mermaid
flowchart TB
  subgraph Untrusted
    Env[Environment variables / .env]
    ExternalCalendar[External calendar package]
    ProviderNetwork[Provider network and payloads]
    UserInput[CLI / future API input]
    ArtifactSource[Serialized model artifact]
  end

  subgraph Boundary
    SettingsValidation[Pydantic settings validation]
    CalendarConversion[Calendar adapter conversion]
    ProviderContract[Capability and page-contract checks]
    RawIntegrity[SHA-256 and byte-count verification]
    Decode[Provider-owned schema decoding]
    Quality[Deterministic quality and reconciliation rules]
    CommandValidation[Application command construction]
    PluginRegistry[Operator-installed plugin registry]
    ArtifactGate[Checksum + explicit trusted-loading policy]
  end

  subgraph TrustedCore
    Domain[Domain invariants]
    Services[Application services]
    Accepted[Accepted point-in-time data]
    Evidence[Datasets, splits, experiments, reports, paper results]
  end

  Env --> SettingsValidation --> Domain
  ExternalCalendar --> CalendarConversion --> Domain
  ProviderNetwork --> ProviderContract --> RawIntegrity --> Decode --> Quality --> Accepted
  UserInput --> CommandValidation --> Services
  PluginRegistry --> Services
  ArtifactSource --> ArtifactGate --> Services
  Services --> Domain
  Services --> Evidence
```

Rules:

- External bytes are preserved before interpretation.
- A checksum proves content identity, not truth or trust.
- Quarantined or rejected data cannot enter normalization.
- Feature and label services consume point-in-time domain inputs, not raw provider objects.
- Model plugins are trusted operator-installed code; arbitrary user-supplied code is prohibited.
- Python/joblib artifact loading is disabled by default and requires explicit trusted-source
  authorization in addition to checksum verification.
- The final holdout is not available to candidate selection.
- Backtest signals are data records, not broker orders, and cannot execute before their
  availability time.
- Secrets and credentials must never appear in payload metadata, manifests, logs, datasets,
  model cards, artifacts, feature/label lineage, or errors.
