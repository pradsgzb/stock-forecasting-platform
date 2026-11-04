# ADR 0017 — Separate retraining, evaluation, promotion, and rollback

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

“Self-correcting” systems are unsafe when a drift alert directly replaces a production model.
Drift does not establish that a challenger is accurate, robust, or operationally safe, and
automatic source-code mutation is neither reproducible nor governable.

## Decision

Use a controlled loop: monitoring may request retraining; retraining creates a candidate;
validation may create a challenger; live outcome evidence compares champion and challenger;
promotion requires minimum samples, minimum improvement, configured approval, and complete
gate evidence. Critical alerts may trigger an audited rollback to the prior active champion.

Human approval is the default. Policy-authorized promotion is disabled by default and cannot
bypass validation evidence, sample requirements, improvement thresholds, or rollback controls.

## Consequences

- Model replacement is slower but materially safer and explainable.
- Monitoring thresholds and promotion policies are versioned operational configuration.
- Teams need runbooks and accountable approvers.
- No component rewrites code or places live trades.
