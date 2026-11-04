# Runbook: training pipeline failure

## Triage

1. Capture training run ID, dataset fingerprint, split-plan fingerprint, candidate, seed, Git commit, and runtime.
2. Determine whether the failure is data validation, resource exhaustion, numerical instability, artifact serialization, metric evaluation, or external infrastructure.
3. Preserve the failed run and logs. Do not delete unsuccessful trials.

## Recovery

- For data failure, correct the upstream data through a new version and rerun from a frozen snapshot.
- For resource failure, enforce a smaller approved search budget; do not silently change the experiment definition.
- For numerical failure, add input validation or a bounded model-specific safeguard and regression test.
- For artifact failure, reject the candidate and verify trusted serialization and checksum policy.

A failed run never changes the champion alias. Restarting must create or resume an idempotent retraining request rather than duplicate promotion actions.
