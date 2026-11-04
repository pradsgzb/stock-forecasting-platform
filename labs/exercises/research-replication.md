# Replicate and challenge a forecasting result

**Exercise ID:** `research-replication`
**Track:** `research-methodology`
**Difficulty:** `advanced`
**Expected focused sessions:** 16

## Objective

Reproduce a result, register all trials, and test whether it survives alternate periods and costs.

## Prerequisites

- transaction-cost-model
- drift-policy

## Extension points

- `docs/governance/experiment-register-template.md`
- `src/stock_predictor/reference`

## Acceptance criteria

- Register unsuccessful as well as successful experiments.
- Preserve one untouched holdout.
- Report uncertainty, costs, limitations, and failed hypotheses.

## Verification

- `uv run --locked stock-predictor reference-scenario --output .local/reference-report.json`
- `uv run --locked pytest tests/integration/test_reference_scenario.py`

## Deliverables

- Reproducibility package
- Experiment register
- Critical findings memo

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
