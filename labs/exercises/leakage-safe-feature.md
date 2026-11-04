# Add a point-in-time feature

**Exercise ID:** `leakage-safe-feature`
**Track:** `time-series`
**Difficulty:** `intermediate`
**Expected focused sessions:** 6

## Objective

Create a versioned feature that cannot observe information after its decision cutoff.

## Prerequisites

- market-provider-adapter

## Extension points

- `src/stock_predictor/application/features/calculators.py`
- `src/stock_predictor/ports/feature_calculator.py`

## Acceptance criteria

- Declare lookback and missing-value behavior.
- Return exact source-bar lineage.
- Include a test that injects future data and proves it is ignored.

## Verification

- `uv run --locked pytest tests/unit/application/features tests/integration/test_market_data_vertical_slice.py`

## Deliverables

- Feature calculator
- Feature documentation
- Leakage regression tests

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
