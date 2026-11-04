# Improve the execution-cost model

**Exercise ID:** `transaction-cost-model`
**Track:** `financial-modeling`
**Difficulty:** `advanced`
**Expected focused sessions:** 10

## Objective

Add a transparent, testable liquidity-aware paper execution policy.

## Prerequisites

- model-plugin

## Extension points

- `src/stock_predictor/ports/backtesting.py`
- `src/stock_predictor/application/backtesting`

## Acceptance criteria

- Never fill before a signal is available.
- Conserve cash and positions under partial fills.
- Demonstrate net results after all configured costs.

## Verification

- `uv run --locked pytest tests/unit/application/backtesting tests/integration/test_model_development_vertical_slice.py`

## Deliverables

- Cost-model strategy
- Property-based accounting tests
- Sensitivity report

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
