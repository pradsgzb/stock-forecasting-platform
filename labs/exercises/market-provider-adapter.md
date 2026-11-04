# Implement a market-data provider adapter

**Exercise ID:** `market-provider-adapter`
**Track:** `data-engineering`
**Difficulty:** `intermediate`
**Expected focused sessions:** 8

## Objective

Add a provider behind the existing SDK while preserving raw payloads and declared limits.

## Prerequisites

- python-domain-extension

## Extension points

- `src/stock_predictor/ports/market_data_provider.py`
- `src/stock_predictor/adapters/market_data`

## Acceptance criteria

- Declare capabilities before network access.
- Pass the provider contract test suite.
- Redact credentials and bound retries.

## Verification

- `uv run --locked pytest tests/contract tests/unit/adapters/market_data`
- `uv run --locked bandit -q -r src -ll`

## Deliverables

- Provider adapter
- Contract tests
- Operational limitation document

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
