# Runbook: model degradation and rollback

## Trigger

Critical performance degradation, calibration failure, feature drift, prediction drift, data-quality incident, or a governance decision invalidates the active champion.

## Containment

1. Freeze new promotion activity for the affected deployment scope.
2. Confirm the alert evidence, minimum sample count, target definition, and outcome maturity.
3. Disable scheduled prediction publication if continuing would create misleading output.
4. Identify the last approved, compatible champion and its feature and preprocessing contracts.

## Rollback

1. Execute the model-registry rollback using an authorized actor and a reason.
2. Verify champion alias, artifact checksum, feature signature, and serving health.
3. Generate a bounded shadow prediction to validate the restored path.
4. Monitor the restored model and compare new outcomes.
5. Preserve the degraded model, deployment history, alert, and rollback event.

Software image rollback is separate. Do not roll back application code unless the incident is caused by the software release.
