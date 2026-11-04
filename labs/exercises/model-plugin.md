# Implement a model plugin

**Exercise ID:** `model-plugin`
**Track:** `machine-learning`
**Difficulty:** `intermediate`
**Expected focused sessions:** 8

## Objective

Add a model through the plugin SDK and compare it with mandatory baselines.

## Prerequisites

- leakage-safe-feature

## Extension points

- `src/stock_predictor/ports/model_plugin.py`
- `src/stock_predictor/application/models/registry.py`

## Acceptance criteria

- `Implement fit, predict, save/load health checks, and deterministic seeding.`
- Report performance against every mandatory baseline.
- Do not inspect the final holdout during tuning.

## Verification

- `uv run --locked pytest tests/unit/adapters/models tests/integration/test_model_development_vertical_slice.py`

## Deliverables

- Model plugin
- Model card
- Comparison report

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
