# Operations Platform Architecture

## Runtime components

```mermaid
flowchart LR
    User[Authorized operator] -->|Bearer JWT| API[FastAPI operations adapter]
    API --> Auth[Authenticator port]
    API --> App[Application services]
    App --> UOW[Operational unit of work]
    UOW --> DB[(PostgreSQL / SQLite test adapter)]
    UOW --> Audit[Hash-chained audit ledger]
    UOW --> Outbox[Transactional outbox]
    Dispatcher[Outbox dispatcher] --> Outbox
    Dispatcher --> Events[Event publisher port]
    API --> Telemetry[Telemetry port]
    Telemetry --> Metrics[Prometheus exposition]
    Telemetry --> Traces[OpenTelemetry spans]
```

## Paper-order transaction

```mermaid
sequenceDiagram
    participant C as API client
    participant A as Authenticator
    participant S as PaperTradingService
    participant U as UnitOfWork
    participant D as Database

    C->>A: Signed bearer token
    A-->>C: Principal and roles
    C->>S: Paper order + idempotency key
    S->>U: Begin transaction
    U->>D: Lock/load account and idempotency record
    S->>S: Validate freshness, cash, position, and limits
    U->>D: Save account, order, fill, audit, and outbox
    U->>D: Commit atomically
    S-->>C: Exact-decimal paper execution
```

## Trust boundaries

- The API never trusts a caller-supplied algorithm, role, owner, account balance, or execution
  result.
- JWT verification keys and database credentials are external secrets.
- The database transaction is the durability boundary for acknowledged writes.
- The event publisher is outside the transaction; the outbox bridges that boundary.
- Metrics and logs must not contain raw tokens, private keys, direct account identifiers, or
  model payloads.
