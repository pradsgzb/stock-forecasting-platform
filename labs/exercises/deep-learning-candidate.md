# Add a bounded deep-learning candidate

**Exercise ID:** `deep-learning-candidate`
**Track:** `deep-learning`
**Difficulty:** `advanced`
**Expected focused sessions:** 14

## Objective

Add an optional neural candidate without weakening baseline, reproducibility, or artifact controls.

## Prerequisites

- model-plugin

## Extension points

- `src/stock_predictor/ports/model_plugin.py`
- `src/stock_predictor/application/training`

## Acceptance criteria

- `Pin random seeds and record hardware/runtime metadata.`
- Bound epochs, memory, and search budget.
- Reject promotion when the model does not beat simple baselines.

## Verification

- `uv run --locked pytest tests/unit/application/training tests/integration/test_model_development_vertical_slice.py`

## Deliverables

- Optional model plugin
- Resource-budget evidence
- Ablation report

## Review questions

- Which invariant does the change introduce or preserve?
- How does the implementation prevent future-data leakage or silent mutation?
- What happens when an input, dependency, or external provider fails?
- Which evidence proves the result is reproducible?
- What limitation remains after this exercise?
