# Add a governed drift detector

**Exercise ID:** `drift-policy`
**Track:** `mlops`
**Difficulty:** `advanced`
**Expected focused sessions:** 8

## Objective

Introduce a versioned drift metric with evidence, alert thresholds, and retraining behavior.

## Prerequisites

- model-plugin

## Extension points

- `src/stock_predictor/application/monitoring/service.py`
- `src/stock_predictor/domain/mlops/monitoring.py`

## Acceptance criteria

- `Define minimum samples and warning/critical thresholds.`
- Persist evidence independently of an alerting vendor.
- Keep human approval required for production promotion.

## Verification

- `uv run --locked pytest tests/unit/application/monitoring tests/integration/test_production_mlops_vertical_slice.py`

## Deliverables

- Drift metric
- Threshold rationale
- Monitoring tests

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
