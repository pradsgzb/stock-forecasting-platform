# Runbook: incorrect or corrected market data

## Trigger

A provider issues a revision, deletes an observation, changes corporate-action data, or internal reconciliation detects materially conflicting content.

## Response

1. Preserve the original raw object and normalized revision.
2. Ingest the correction as a new immutable provider revision or tombstone.
3. Resolve the correction using its actual availability time; do not rewrite what was known historically.
4. Identify affected feature snapshots, datasets, experiments, predictions, outcomes, and reports through lineage.
5. Recalculate only artifacts whose policy permits correction and create new versions.
6. Do not mutate historical predictions that were generated before the correction arrived.
7. Assess whether published research, monitoring, or model-promotion evidence must be withdrawn.

## Closure

Document source, correction timing, affected artifacts, replacement versions, decision owner, and whether model retraining is required.
