# Model-Risk Principles

All model, serving, feedback, and backtest work must follow these rules:

1. A forecast is an uncertain estimate, not a promise.
2. Every advanced model must be compared with appropriate naive baselines out of sample.
3. Random train/test splits are prohibited for time-dependent market data.
4. Every feature and label must prove point-in-time availability and source lineage.
5. Historical universe membership, symbol changes, corrections, and delistings must be retained.
6. Overlapping labels must be purged from validation boundaries.
7. A final holdout must remain untouched until candidate selection is complete.
8. All attempted candidates and failures must be recorded, not only the winner.
9. Hyperparameter search must be bounded and reproducible.
10. Metrics must be reported with sample count, direction, and uncertainty where practical.
11. Explainability is evidence about model behavior, not proof of causation.
12. Backtests must model signal availability, permitted execution time, transaction costs,
    liquidity, turnover, cash, concentration, and drawdown.
13. Paper performance is not proof of deployable or profitable performance.
14. Production predictions must be stored before outcomes become known.
15. Historical predictions cannot be edited after the fact; corrections append new evidence.
16. Outcome corrections preserve prior revisions and source-label lineage.
17. Retraining produces a candidate and challenger; it does not silently replace a champion.
18. Model promotion requires validation gates, sufficient outcomes, minimum improvement, and
    configured authorization.
19. Drift is a diagnostic signal, not proof that a challenger is better.
20. Model promotion and rollback are policy-controlled, attributable, and auditable.
21. Critical alerts may roll back only the current champion to a recorded predecessor.
22. Serialized model artifacts are executable content and require a trusted source.
23. Automatic promotion is disabled by default and cannot bypass evidence requirements.
24. The system must not rewrite its own source code.
25. Live trading requires a separate safety, security, legal, and regulatory design review.
