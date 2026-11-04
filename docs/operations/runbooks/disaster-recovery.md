# Runbook: disaster recovery

## Preconditions

- Documented recovery point and recovery time objectives.
- Tested backups for database, immutable object storage, model artifacts, release evidence, and configuration.
- Infrastructure reproducible from reviewed Terraform and deployment manifests.
- Restorable identity and secret references without storing raw secrets in backups.

## Recovery sequence

1. Declare the incident and select the recovery region or environment.
2. Freeze writes and preserve the last known durable checkpoints.
3. Provision network, identity, database, object storage, and compute from source-controlled infrastructure.
4. Restore the database to the approved recovery point.
5. Restore or reconnect immutable data and model artifacts; verify checksums.
6. Apply forward-compatible migrations.
7. Deploy the last approved software image by digest.
8. Restore the champion model alias by immutable model version.
9. Reconcile audit chain, outbox, ingestion checkpoints, predictions, and outcomes.
10. Run liveness, readiness, reference smoke, and bounded operational tests.
11. Obtain incident-command approval before resuming scheduled work.

## Validation

A recovery exercise must record actual recovery times, data loss relative to the objective, checksum results, unresolved gaps, and corrective actions. A backup that has not been restored and verified is not accepted recovery evidence.
