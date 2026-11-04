# Continuous training operations

Continuous training is a controlled challenger workflow, not unrestricted self-modification.

## Trigger sources

- scheduled evaluation;
- minimum new outcomes reached;
- critical data or feature drift;
- material calibration or performance degradation;
- approved market-regime review; or
- an authorized manual request.

## Required sequence

1. Freeze a new point-in-time dataset snapshot.
2. Train configured candidates within bounded budgets.
3. Evaluate purged walk-forward folds and untouched holdout data.
4. Run cost-aware paper backtests.
5. Register accepted candidates as challengers.
6. Compare challenger and champion over equivalent evidence windows.
7. Obtain required model-validation, risk-owner, and deployment approvals.
8. Promote by immutable model version.
9. Monitor the new champion.
10. Roll back when a critical policy threshold is breached.

No workflow may overwrite a historical model, prediction, outcome, or evaluation. Corrections are append-only.

## Qualification workflow

The scheduled **Continuous Training Qualification** workflow runs the synthetic end-to-end scenario and retains its report. It proves pipeline integration but does not claim market predictability and does not promote a production model.

## Production integration

A production scheduler should submit a durable retraining request to the application using approved data and an exact deployment scope. The worker must use workload identity, immutable configuration, and an approved model artifact store. Do not place provider keys, model approvals, or promotion decisions in workflow source.
