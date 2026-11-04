# Local Development Runbook

## Bootstrap

```bash
uv sync --all-groups
uv run --locked pre-commit install --install-hooks
```

On Windows use `scripts/bootstrap.ps1`; on Linux/macOS use `scripts/bootstrap.sh`.

## Verify the environment

```bash
uv run --locked stock-predictor doctor
```

The command prints non-secret runtime and adapter information.

## Run a session query

```bash
uv run --locked stock-predictor session --mic XNYS --date 2025-07-03
```

## Run checks

```bash
./scripts/check.sh
```

or:

```powershell
./scripts/check.ps1
```

## Troubleshooting

- If `zoneinfo` cannot locate a time zone on Windows, confirm the `tzdata` dependency is
  installed through `uv sync`.
- If a calendar MIC is not enabled, add an explicit exchange configuration and an adapter
  with authoritative rules; do not reuse another exchange's calendar.
- If configuration validation fails, compare environment names with `.env.example`.

## Release verification

After generating and committing `uv.lock`, run the stricter release gate:

```bash
./scripts/release-check.sh
```

or on Windows:

```powershell
./scripts/release-check.ps1
```

This gate refuses to run without a lockfile and uses lock-enforcing dependency commands.

## Local data directories

The default composition root creates these paths under `SP_STORAGE__DATA_ROOT`:

```text
.local/data/
├── raw-objects/       # write-once SHA-256 provider payloads
└── ingestion-catalog/ # manifests and resumable checkpoints
```

Delete local test data only when no reproducibility or audit requirement applies. A production
adapter should use managed object storage and transactional persistence rather than treating
these local directories as a production data lake.

## Adding a provider adapter

1. Implement or subclass the provider SDK contract.
2. Declare exchanges, frequencies, adjustments, request limits, pagination, and correction
   capabilities.
3. Return exact response bytes in `MarketDataPage`.
4. Decode only pages owned by the adapter.
5. Add capability, pagination, retry, malformed-payload, and fixture-based contract tests.
6. Register the adapter explicitly in the composition root for the target process.

Do not put API keys in adapter configuration objects that may be logged. Resolve credentials
through the secret-provider boundary.
