# ADR 0012 — Use purged walk-forward validation and an untouched final holdout

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

Random cross-validation leaks temporal information in market data. Overlapping target horizons
can also allow training outcomes to extend into a validation period even when rows are ordered.
Repeatedly inspecting one final period during tuning converts that period into development data.

## Decision

All supervised time-dependent datasets use an explicit split plan containing expanding or
rolling walk-forward folds, a configurable train/validation gap, label-overlap purging, optional
embargo, and one final holdout. Candidate selection uses development folds only. The selected
candidate is then refit on all development rows and evaluated once on the holdout.

## Consequences

- Effective sample size is lower than with random splitting.
- Split plans are versioned and fingerprinted evidence.
- Training fails when purging leaves an invalid fold.
- Holdout metrics cannot be used to select the candidate within the same training run.
